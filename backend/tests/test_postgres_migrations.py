import os
import sys
import shutil
import subprocess
import time
from pathlib import Path
import pytest
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app, _get_public_health_data, _get_detailed_health_data
from app.config import settings
from app.database import get_db, SessionLocal
from app.migrations import run_db_migrations, get_schema_info, check_schema_health

PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")
PG_PORT = 5433
PG_USER = "postgres"
PG_DATA = Path(os.environ.get("TEMP", "C:/Temp")) / "smartcart_pg_test_cluster"
TEST_DB_NAME = "cart_legacy_pg_test"
PG_URL = f"postgresql://{PG_USER}@localhost:{PG_PORT}/{TEST_DB_NAME}"
POSTGRES_BASE_URL = f"postgresql://{PG_USER}@localhost:{PG_PORT}/postgres"


@pytest.fixture(scope="module")
def postgres_service():
    """
    Connects to or spins up an isolated real PostgreSQL 18 cluster on port 5433 for testing.
    """
    # 0. Check if PostgreSQL on port 5433 is already running
    try:
        conn = psycopg2.connect(dbname="postgres", user=PG_USER, host="localhost", port=PG_PORT)
        conn.close()
        yield {
            "port": PG_PORT,
            "user": PG_USER,
            "base_url": POSTGRES_BASE_URL,
            "test_db_url": PG_URL
        }
        return
    except Exception:
        pass

    initdb_exe = PG_BIN / "initdb.exe"
    pg_ctl_exe = PG_BIN / "pg_ctl.exe"

    if not initdb_exe.exists():
        pytest.skip("PostgreSQL 18 binaries not found on this system.")

    # 1. Clean existing temp directory if any
    if PG_DATA.exists():
        try:
            shutil.rmtree(PG_DATA)
        except Exception:
            pass

    # 2. Run initdb
    init_cmd = [
        str(initdb_exe),
        "-D", str(PG_DATA),
        "-U", PG_USER,
        "-A", "trust",
        "--no-locale",
        "-E", "UTF8"
    ]
    res = subprocess.run(init_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.fail(f"initdb failed: {res.stderr}")

    # 3. Start PostgreSQL on port 5433 with log file
    log_file = PG_DATA / "server.log"
    start_cmd = [
        str(pg_ctl_exe),
        "start",
        "-D", str(PG_DATA),
        "-l", str(log_file),
        "-o", f"-p {PG_PORT}",
        "-w"
    ]
    res_start = subprocess.run(start_cmd, capture_output=True, text=True)
    if res_start.returncode != 0:
        pytest.fail(f"pg_ctl start failed: {res_start.stderr}")

    # Wait for PostgreSQL to be ready
    ready = False
    for _ in range(15):
        try:
            conn = psycopg2.connect(dbname="postgres", user=PG_USER, host="localhost", port=PG_PORT)
            conn.close()
            ready = True
            break
        except Exception:
            time.sleep(0.5)

    if not ready:
        subprocess.run([str(pg_ctl_exe), "stop", "-D", str(PG_DATA), "-m", "immediate", "-w"])
        pytest.fail("PostgreSQL test server failed to accept connections.")

    yield {
        "port": PG_PORT,
        "user": PG_USER,
        "base_url": POSTGRES_BASE_URL,
        "test_db_url": PG_URL
    }

    # Teardown: Stop server and remove cluster data
    stop_cmd = [
        str(pg_ctl_exe),
        "stop",
        "-D", str(PG_DATA),
        "-m", "fast",
        "-w"
    ]
    subprocess.run(stop_cmd, capture_output=True, text=True)
    try:
        shutil.rmtree(PG_DATA, ignore_errors=True)
    except Exception:
        pass
        pytest.fail("PostgreSQL test server failed to accept connections.")

    yield {
        "port": PG_PORT,
        "user": PG_USER,
        "base_url": POSTGRES_BASE_URL,
        "test_db_url": PG_URL
    }

    # Teardown: Stop server and remove cluster data
    stop_cmd = [
        str(pg_ctl_exe),
        "stop",
        "-D", str(PG_DATA),
        "-m", "fast",
        "-w"
    ]
    subprocess.run(stop_cmd, capture_output=True, text=True)
    try:
        shutil.rmtree(PG_DATA, ignore_errors=True)
    except Exception:
        pass


def test_real_postgres_migration_from_legacy_create_all_schema(postgres_service):
    """
    Test against a REAL PostgreSQL 18 database initialized with the old create_all() schema:
    1. Creates fresh database 'cart_legacy_pg_test'.
    2. Builds the legacy schema: core tables exist, BUT alembic_version does not,
       and cart_sessions does NOT have session_token.
    3. Confirms alembic_version is absent and /health reports schema_ok=False.
    4. Runs run_db_migrations('head') which detects the legacy unversioned state,
       adds baseline pieces idempotently, stamps baseline (d54e41411396),
       and upgrades to head (f3a4b5c6d7e8).
    5. Confirms /health returns status 200 with schema_ok=True, current_revision='f3a4b5c6d7e8',
       head_revision='f3a4b5c6d7e8', and migration_error=None.
    6. Verifies that cart_sessions.session_token was added and indexed.
    7. Verifies that pre-existing data is preserved.
    """
    # Step 1: Create fresh test database in PostgreSQL
    base_conn = psycopg2.connect(dbname="postgres", user=PG_USER, host="localhost", port=PG_PORT)
    base_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = base_conn.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME};")
    cursor.execute(f"CREATE DATABASE {TEST_DB_NAME};")
    cursor.close()
    base_conn.close()

    engine = create_engine(PG_URL)

    # Step 2: Build legacy schema (mimicking create_all() before Alembic was introduced)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE users (
                    id VARCHAR(36) PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(100) NOT NULL,
                    role VARCHAR(20) DEFAULT 'STAFF' NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );

                CREATE TABLE carts (
                    id VARCHAR(36) PRIMARY KEY,
                    cart_number VARCHAR(20) UNIQUE NOT NULL,
                    qr_code_token VARCHAR(100) UNIQUE NOT NULL,
                    status VARCHAR(20) DEFAULT 'IDLE' NOT NULL,
                    battery_level INTEGER DEFAULT 100 NOT NULL,
                    camera_status VARCHAR(20) DEFAULT 'ONLINE' NOT NULL,
                    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );

                CREATE TABLE products (
                    id VARCHAR(36) PRIMARY KEY,
                    barcode VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    brand VARCHAR(100) NOT NULL,
                    category VARCHAR(100) NOT NULL,
                    price FLOAT NOT NULL,
                    discount_price FLOAT,
                    weight_grams INTEGER DEFAULT 100 NOT NULL,
                    tax_rate FLOAT DEFAULT 5.0 NOT NULL,
                    stock_quantity INTEGER DEFAULT 100 NOT NULL,
                    primary_image_url TEXT,
                    is_active BOOLEAN DEFAULT TRUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );

                -- Legacy cart_sessions: WITHOUT session_token
                CREATE TABLE cart_sessions (
                    id VARCHAR(36) PRIMARY KEY,
                    cart_id VARCHAR(36) REFERENCES carts(id) ON DELETE CASCADE NOT NULL,
                    customer_phone VARCHAR(20),
                    status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    subtotal_amount FLOAT DEFAULT 0.0 NOT NULL,
                    total_tax FLOAT DEFAULT 0.0 NOT NULL,
                    total_discount FLOAT DEFAULT 0.0 NOT NULL,
                    total_amount FLOAT DEFAULT 0.0 NOT NULL,
                    item_count INTEGER DEFAULT 0 NOT NULL
                );

                CREATE TABLE cart_items (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) REFERENCES cart_sessions(id) ON DELETE CASCADE NOT NULL,
                    product_id VARCHAR(36) REFERENCES products(id) NOT NULL,
                    quantity INTEGER DEFAULT 1 NOT NULL,
                    unit_price FLOAT NOT NULL,
                    status VARCHAR(30) DEFAULT 'PENDING' NOT NULL,
                    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    verified_at TIMESTAMP,
                    confidence_score FLOAT,
                    verification_evidence_url TEXT
                );

                CREATE TABLE alerts (
                    id VARCHAR(36) PRIMARY KEY,
                    cart_id VARCHAR(36) REFERENCES carts(id) ON DELETE CASCADE NOT NULL,
                    session_id VARCHAR(36) REFERENCES cart_sessions(id) ON DELETE SET NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    severity VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL,
                    message TEXT NOT NULL,
                    evidence_snapshot_url TEXT,
                    status VARCHAR(20) DEFAULT 'OPEN' NOT NULL,
                    resolved_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                    resolution_notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    resolved_at TIMESTAMP
                );

                CREATE TABLE transactions (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) REFERENCES cart_sessions(id) ON DELETE CASCADE UNIQUE NOT NULL,
                    payment_method VARCHAR(50) DEFAULT 'UPI' NOT NULL,
                    payment_gateway_ref VARCHAR(100),
                    amount FLOAT NOT NULL,
                    status VARCHAR(20) DEFAULT 'SUCCESS' NOT NULL,
                    receipt_number VARCHAR(50) UNIQUE NOT NULL,
                    receipt_pdf_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );

                -- Seed existing data to prove non-destructive migration
                INSERT INTO users (id, email, password_hash, full_name, role)
                VALUES ('user-seed-01', 'existing_staff@smartcart.internal', 'hash123', 'Staff Member', 'STAFF');

                INSERT INTO carts (id, cart_number, qr_code_token)
                VALUES ('cart-seed-01', 'CART-PG-01', 'QR-PG-01');

                INSERT INTO products (id, barcode, name, brand, category, price)
                VALUES ('prod-seed-01', '8901234567890', 'Organic Green Tea', 'EcoBrand', 'Beverages', 4.99);

                INSERT INTO cart_sessions (id, cart_id)
                VALUES ('sess-seed-01', 'cart-seed-01');
            """))

    # Step 3: Verify initial state in PostgreSQL
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert "cart_sessions" in table_names
    assert "alembic_version" not in table_names, "alembic_version table must NOT exist in the legacy schema"
    assert "maintenance_flags" not in table_names

    cart_sess_cols = {c["name"] for c in inspector.get_columns("cart_sessions")}
    assert "session_token" not in cart_sess_cols, "session_token must NOT exist in legacy cart_sessions"

    # Step 4: Verify get_schema_info reports unversioned status
    with engine.connect() as conn:
        schema_info_before = get_schema_info(connection=conn)
        assert schema_info_before["current_revision"] is None
        assert schema_info_before["head_revision"] == "f3a4b5c6d7e8"
        assert not schema_info_before["is_up_to_date"]
        assert "Database unversioned" in schema_info_before["migration_error"]

    # Step 5: Temporarily point settings.DATABASE_URL and app.database to our PostgreSQL test DB
    import app.database as app_db
    from sqlalchemy.orm import sessionmaker
    old_db_url = settings.DATABASE_URL
    old_engine = app_db.engine
    old_session_local = app_db.SessionLocal

    settings.DATABASE_URL = PG_URL
    app_db.engine = engine
    app_db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        # Step 6: Run run_db_migrations("head")
        success = run_db_migrations(target="head")
        assert success is True, "run_db_migrations('head') should succeed on unversioned database"

        # Step 7: Inspect migrated PostgreSQL schema
        inspector_after = inspect(engine)
        table_names_after = set(inspector_after.get_table_names())
        assert "alembic_version" in table_names_after, "alembic_version must now exist"
        assert "maintenance_flags" in table_names_after, "maintenance_flags must now exist"

        cart_sess_cols_after = {c["name"] for c in inspector_after.get_columns("cart_sessions")}
        assert "session_token" in cart_sess_cols_after, "session_token column must exist on cart_sessions"

        # Verify index exists on session_token
        cart_indexes = {ix["name"] for ix in inspector_after.get_indexes("cart_sessions")}
        assert "ix_cart_sessions_session_token" in cart_indexes

        # Verify performance indexes exist
        assert "ix_cart_sessions_cart_id" in cart_indexes
        assert "ix_cart_sessions_status" in cart_indexes

        # Step 8: Verify schema info reports up-to-date at head
        with engine.connect() as conn:
            schema_info_after = get_schema_info(connection=conn)
            assert schema_info_after["is_up_to_date"] is True
            assert schema_info_after["current_revision"] == "f3a4b5c6d7e8"
            assert schema_info_after["head_revision"] == "f3a4b5c6d7e8"
            assert schema_info_after["migration_error"] is None

        # Step 9: Verify existing data was preserved
        with engine.connect() as conn:
            user_count = conn.execute(text("SELECT COUNT(*) FROM users;")).scalar()
            assert user_count == 1
            cart_count = conn.execute(text("SELECT COUNT(*) FROM carts;")).scalar()
            assert cart_count == 1
            prod_count = conn.execute(text("SELECT COUNT(*) FROM products;")).scalar()
            assert prod_count == 1
            sess_count = conn.execute(text("SELECT COUNT(*) FROM cart_sessions;")).scalar()
            assert sess_count == 1

        # Step 10: Verify public minimal /health output and authenticated detailed diagnostics
        public_health = _get_public_health_data()
        detailed_health = _get_detailed_health_data()
        print("\n--- LIVE POSTGRESQL MINIMAL /health OUTPUT ---")
        import json
        print(json.dumps(public_health, indent=2))
        print("\n--- LIVE POSTGRESQL DETAILED /admin/system-health OUTPUT ---")
        print(json.dumps(detailed_health, indent=2))

        assert set(public_health.keys()) == {"status", "database_ok", "schema_ok", "model_loaded"}
        assert public_health["schema_ok"] is True
        assert public_health["database_ok"] is True
        assert public_health["status"] in ("HEALTHY", "STARTING")

        assert detailed_health["schema_ok"] is True
        assert detailed_health["current_revision"] == "f3a4b5c6d7e8"
        assert detailed_health["head_revision"] == "f3a4b5c6d7e8"
        assert detailed_health["migration_error"] is None
        assert detailed_health["database_ok"] is True

    finally:
        settings.DATABASE_URL = old_db_url
        app_db.engine = old_engine
        app_db.SessionLocal = old_session_local
        engine.dispose()
