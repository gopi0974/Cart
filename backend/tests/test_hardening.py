import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.config import settings
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.models.session import CartSession
from app.utils.security import hash_password, create_access_token, decode_access_token
from app.api.v1.auth import login_rate_limiter

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def setup_test_users():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    # Reset rate limiter state before each test
    with login_rate_limiter._lock:
        login_rate_limiter._failures.clear()

    db = TestingSessionLocal()
    try:
        admin = User(
            id="h-admin-id",
            email="admin.hardening@smartcart.internal",
            password_hash=hash_password("HardeningAdmin!2026"),
            full_name="Hardening Admin",
            role="ADMIN",
            is_active=True
        )
        staff = User(
            id="h-staff-id",
            email="staff.hardening@smartcart.internal",
            password_hash=hash_password("HardeningStaff!2026"),
            full_name="Hardening Staff",
            role="STAFF",
            is_active=True
        )
        cart = Cart(
            id="h-cart-id",
            cart_number="CART-H-01",
            qr_code_token="QR-H-01",
            is_enabled=True,
            status="ACTIVE"
        )
        session = CartSession(
            id="h-session-id",
            cart_id="h-cart-id",
            session_token="h_session_token_123",
            status="ACTIVE"
        )
        db.add_all([admin, staff, cart, session])
        db.commit()
    finally:
        db.close()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_jwt_token_expiry_is_8_hours():
    """Verify that staff JWT access tokens are configured with 8 hours (480 minutes) expiry."""
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 480

    token = create_access_token(data={"sub": "admin.hardening@smartcart.internal", "role": "ADMIN"})
    payload = decode_access_token(token)
    assert payload is not None
    assert "exp" in payload


def test_login_rate_limiting_blocks_after_5_failed_attempts():
    """
    Submitting 5 consecutive incorrect passwords must succeed with 401,
    and the 6th attempt must return HTTP 429 Too Many Requests.
    """
    client = TestClient(app)

    # 5 failed attempts
    for attempt in range(1, 6):
        res = client.post("/api/v1/auth/login", json={
            "email": "admin.hardening@smartcart.internal",
            "password": "WrongPassword!999"
        })
        assert res.status_code == 401, f"Attempt {attempt} should return 401"

    # 6th attempt should be blocked by rate limiter with 429
    blocked_res = client.post("/api/v1/auth/login", json={
        "email": "admin.hardening@smartcart.internal",
        "password": "HardeningAdmin!2026"  # Even with correct password, blocked
    })
    assert blocked_res.status_code == 429
    assert "Too many failed login attempts" in blocked_res.json()["detail"]


def test_simulate_action_rejected_when_use_mock_false(monkeypatch):
    """
    POST /vision/simulate-action must return 403 when USE_MOCK=false,
    even for an authenticated Admin.
    """
    monkeypatch.setattr(settings, "USE_MOCK", False)
    client = TestClient(app)
    admin_token = create_access_token(data={"sub": "admin.hardening@smartcart.internal", "role": "ADMIN"})

    res = client.post(
        "/api/v1/vision/simulate-action",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "cart_id": "CART-H-01",
            "action_type": "PLACE_CORRECT"
        }
    )
    assert res.status_code == 403
    assert "simulation is disabled" in res.json()["detail"]


def test_simulate_action_rejected_for_staff_role(monkeypatch):
    """
    POST /vision/simulate-action must return 403 for STAFF role even if USE_MOCK=true.
    """
    monkeypatch.setattr(settings, "USE_MOCK", True)
    client = TestClient(app)
    staff_token = create_access_token(data={"sub": "staff.hardening@smartcart.internal", "role": "STAFF"})

    res = client.post(
        "/api/v1/vision/simulate-action",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={
            "cart_id": "CART-H-01",
            "action_type": "PLACE_CORRECT"
        }
    )
    assert res.status_code == 403


def test_validate_production_secrets_raises_on_default_or_unset():
    """Startup secret validation must raise when DEMO_MODE=false and SECRET_KEY or QR_SIGNING_SECRET is default/empty."""
    from app.config import Settings, validate_production_secrets, DEFAULT_SECRET_KEY, DEFAULT_QR_SIGNING_SECRET

    bad_jwt = Settings(DEMO_MODE=False, SECRET_KEY=DEFAULT_SECRET_KEY, QR_SIGNING_SECRET="custom-qr-secret-123456")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_secrets(bad_jwt)

    bad_qr = Settings(DEMO_MODE=False, SECRET_KEY="custom-jwt-secret-123456", QR_SIGNING_SECRET=DEFAULT_QR_SIGNING_SECRET)
    with pytest.raises(RuntimeError, match="QR_SIGNING_SECRET"):
        validate_production_secrets(bad_qr)

    ok_prod = Settings(DEMO_MODE=False, SECRET_KEY="custom-jwt-secret-123456", QR_SIGNING_SECRET="custom-qr-secret-123456")
    validate_production_secrets(ok_prod)

    ok_demo = Settings(DEMO_MODE=True, SECRET_KEY=DEFAULT_SECRET_KEY, QR_SIGNING_SECRET=DEFAULT_QR_SIGNING_SECRET)
    validate_production_secrets(ok_demo)


def test_git_commit_hash_fallback_is_unknown(monkeypatch):
    """get_git_commit_hash must read RENDER_GIT_COMMIT and fall back to 'unknown', never a hardcoded hash."""
    from app.main import get_git_commit_hash
    import subprocess

    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no git")))
    assert get_git_commit_hash() == "unknown"

    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567890")
    assert get_git_commit_hash() == "abcdef1"


def test_regenerate_qr_audit_log_never_stores_token():
    """Regenerating a cart QR code must log the event in AuditLog without writing new_qr_token."""
    from app.models.cart import Cart
    from app.models.transaction import AuditLog

    db = TestingSessionLocal()
    try:
        cart = Cart(id="cart-qr-audit-1", cart_number="CART-QR-1", qr_code_token="QR-OLD", is_enabled=True, status="IDLE")
        db.add(cart)
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    admin_token = create_access_token(data={"sub": "admin.hardening@smartcart.internal", "role": "ADMIN"})
    res = client.post(
        "/api/v1/admin/carts/cart-qr-audit-1/regenerate-qr",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    new_token = res.json()["qr_code_token"]

    db = TestingSessionLocal()
    try:
        log = db.query(AuditLog).filter(AuditLog.action == "REGENERATE_CART_QR", AuditLog.entity_id == "cart-qr-audit-1").first()
        assert log is not None
        assert new_token not in (log.details_json or "")
        assert "new_qr_token" not in (log.details_json or "")
        assert "QR_TOKEN_REGENERATED" in (log.details_json or "")
    finally:
        db.close()
