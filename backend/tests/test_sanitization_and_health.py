import os
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app, _get_public_health_data, _get_detailed_health_data
from app.config import settings
from app.utils.sanitization import sanitize_secrets, mask_url
from app.migrations import get_alembic_config
from app.utils.security import create_access_token, hash_password
from app.database import get_db, Base
from app.models.user import User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.database as app_db

# Isolated in-memory SQLite database for authentication dependency overrides
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

# Seed staff user in test database
with TestingSessionLocal() as session:
    if not session.query(User).filter(User.email == "staff@smartcart.internal").first():
        staff = User(
            id="test-staff-uuid",
            email="staff@smartcart.internal",
            password_hash=hash_password("StaffPass123"),
            full_name="Staff Diagnostic Tester",
            role="STAFF",
            is_active=True
        )
        session.add(staff)
        session.commit()


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_test_db():
    app.dependency_overrides[get_db] = override_get_db
    old_engine = app_db.engine
    old_session = app_db.SessionLocal
    app_db.engine = test_engine
    app_db.SessionLocal = TestingSessionLocal
    yield
    app_db.engine = old_engine
    app_db.SessionLocal = old_session
    app.dependency_overrides[get_db] = override_get_db


def test_public_health_output_is_minimal():
    """
    Validates that the public /health endpoint exposes ONLY the minimal allowed fields:
    {status, database_ok, schema_ok, model_loaded}.
    Internal diagnostic fields (revisions, migration_error, memory, vector counts)
    must NEVER be exposed to the public.
    """
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()

    # Allowed public keys
    allowed_keys = {"status", "database_ok", "schema_ok", "model_loaded"}
    assert set(data.keys()) == allowed_keys, f"Public /health contained unexpected keys: {set(data.keys()) - allowed_keys}"

    # Forbidden diagnostic fields
    forbidden_keys = [
        "current_revision",
        "head_revision",
        "migration_error",
        "memory_rss_mb",
        "vectors_count",
        "products_enrolled",
        "model_name",
        "vector_dimension",
        "storage_ok",
        "demo_mode",
        "use_mock"
    ]
    for key in forbidden_keys:
        assert key not in data, f"Forbidden key '{key}' leaked in public /health response!"


def test_health_never_contains_password_or_secrets():
    """
    Validates that /health never contains passwords or connection strings,
    even when DATABASE_URL has a sensitive secret password.
    """
    sensitive_password = "SuperSecretP%40ssw%25rd999"
    test_db_url = f"postgresql://appuser:{sensitive_password}@db.internal.cloud:5432/smartcart_prod"
    
    old_url = settings.DATABASE_URL
    settings.DATABASE_URL = test_db_url

    try:
        client = TestClient(app)
        response = client.get("/health")
        content_text = response.text

        assert sensitive_password not in content_text, "Sensitive password was leaked in /health!"
        assert "appuser" not in content_text, "Database username was leaked in /health!"
        assert "db.internal.cloud" not in content_text, "Database host was leaked in /health!"
    finally:
        settings.DATABASE_URL = old_url


def test_mask_url_and_sanitize_secrets_helper():
    """
    Validates that the sanitization helper masks connection strings with passwords,
    including percent signs, @ symbols, query parameters, and bearer tokens.
    """
    # 1. PostgreSQL URL with percent-encoded characters
    url_1 = "postgresql://postgres:Cart0974%40Gopi%21@db.supabase.co:5432/postgres?sslmode=require"
    masked_1 = mask_url(url_1)
    assert "Cart0974" not in masked_1
    assert "Gopi" not in masked_1
    assert "postgresql://postgres:***@db.supabase.co:5432/postgres?sslmode=require" in masked_1

    # 2. URL with percent sign and @ sign
    url_2 = "postgresql://myuser:p%40ss%25word123@localhost:5432/db"
    masked_2 = mask_url(url_2)
    assert "p%40ss%25word123" not in masked_2
    assert "postgresql://myuser:***@localhost:5432/db" in masked_2

    # 3. Exception error message containing raw connection string
    error_str = "Failed to connect to postgresql://admin:MyPass%231@prod.db.com:5432/mydb: connection refused"
    sanitized_err = sanitize_secrets(error_str)
    assert "MyPass%231" not in sanitized_err
    assert "postgresql://admin:***@prod.db.com:5432/mydb" in sanitized_err

    # 4. Bearer tokens in headers
    auth_header = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"
    sanitized_auth = sanitize_secrets(auth_header)
    assert "eyJhbGciOiJIUzI1Ni" not in sanitized_auth
    assert "Bearer ***" in sanitized_auth


def test_alembic_config_with_percent_and_at_password():
    """
    Validates that Alembic ConfigParser handles passwords containing '%' and '@'
    without throwing InterpolationSyntaxError.
    """
    password_with_percent_and_at = "Complex%25Pass%40word%2199"
    test_url = f"postgresql://dbuser:{password_with_percent_and_at}@localhost:5432/testdb"

    # get_alembic_config must escape '%' as '%%' for ConfigParser
    cfg = get_alembic_config(custom_url=test_url)

    # Reading sqlalchemy.url through configparser must NOT raise InterpolationSyntaxError
    retrieved_url = cfg.get_main_option("sqlalchemy.url")
    assert retrieved_url == test_url, "Retrieved URL did not match the original unescaped URL!"
    assert "%" in retrieved_url, "Percent sign was incorrectly lost"

    # Direct target_url attribute check
    assert cfg.attributes.get("target_url") == test_url


def test_admin_system_health_requires_authentication():
    """
    Validates:
    1. Unauthenticated requests to /admin/system-health return 401 Unauthorized.
    2. Authenticated requests with a valid staff token return 200 with full diagnostic fields.
    3. Any error field in /admin/system-health is strictly sanitized.
    """
    client = TestClient(app)

    # 1. Unauthenticated request must be rejected with 401
    unauth_resp = client.get("/admin/system-health")
    assert unauth_resp.status_code == 401, f"Expected 401, got {unauth_resp.status_code}"

    unauth_api_resp = client.get("/api/v1/admin/system-health")
    assert unauth_api_resp.status_code == 401, f"Expected 401, got {unauth_api_resp.status_code}"

    # 2. Authenticated request with staff JWT token must succeed with 200
    staff_token = create_access_token(data={"sub": "staff@smartcart.internal", "role": "STAFF"})
    headers = {"Authorization": f"Bearer {staff_token}"}

    auth_resp = client.get("/admin/system-health", headers=headers)
    assert auth_resp.status_code == 200, f"Expected 200, got {auth_resp.status_code}: {auth_resp.text}"

    data = auth_resp.json()
    assert "status" in data
    assert "database_ok" in data
    assert "schema_ok" in data
    assert "model_loaded" in data
    assert "current_revision" in data
    assert "head_revision" in data
    assert "migration_error" in data
    assert "memory_rss_mb" in data

    # 3. Assert no password or unmasked connection string appears in the response
    assert "postgresql://" not in auth_resp.text or ":***@" in auth_resp.text
