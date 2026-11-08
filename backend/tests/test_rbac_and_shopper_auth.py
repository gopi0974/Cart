import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession
from app.models.transaction import ModelVersion, AuditLog
from app.utils.security import hash_password, create_access_token

# Standalone fast in-memory SQLite database for test suite isolation
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def ensure_db_override():
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module")
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def test_users(db_session):
    """Seed test users for ADMIN, MANAGER, and STAFF roles."""
    roles = {
        "ADMIN": "test_admin_rbac@smartcart.ai",
        "MANAGER": "test_mgr_rbac@smartcart.ai",
        "STAFF": "test_staff_rbac@smartcart.ai"
    }
    tokens = {}
    users = {}

    for role, email in roles.items():
        user = db_session.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                password_hash=hash_password("TestSecret123!"),
                full_name=f"Test {role.title()} User",
                role=role,
                is_active=True
            )
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
        users[role] = user
        tokens[role] = create_access_token({"sub": user.email, "role": role})

    return {"users": users, "tokens": tokens}

@pytest.fixture(scope="module")
def sample_cart(db_session):
    """Ensure at least one cart is available for testing."""
    cart = db_session.query(Cart).filter(Cart.cart_number == "CART-TEST-001").first()
    if not cart:
        cart = Cart(
            cart_number="CART-TEST-001",
            qr_code_token="QR-CART-TEST-001",
            is_enabled=True,
            status="IDLE",
            battery_level=100,
            camera_status="ONLINE"
        )
        db_session.add(cart)
        db_session.commit()
        db_session.refresh(cart)
    return cart

@pytest.fixture(scope="module")
def sample_model(db_session):
    """Ensure at least two model checkpoints exist for activation & rollback."""
    m1 = db_session.query(ModelVersion).filter(ModelVersion.version_tag == "v1.0.0-test").first()
    if not m1:
        m1 = ModelVersion(
            version_tag="v1.0.0-test",
            accuracy=0.982,
            is_active=True
        )
        db_session.add(m1)

    m2 = db_session.query(ModelVersion).filter(ModelVersion.version_tag == "v0.9.0-test").first()
    if not m2:
        m2 = ModelVersion(
            version_tag="v0.9.0-test",
            accuracy=0.965,
            is_active=False
        )
        db_session.add(m2)

    db_session.commit()
    db_session.refresh(m1)
    db_session.refresh(m2)
    return {"m1": m1, "m2": m2}


# =========================================================================
# TEST SUITE 1: 401 UNAUTHENTICATED REQUESTS
# =========================================================================
def test_unauthenticated_requests_return_401():
    """Verify that protected admin endpoints return 401 when no token is supplied."""
    r1 = client.get("/api/v1/admin/overview")
    assert r1.status_code == 401, f"Expected 401, got {r1.status_code}: {r1.text}"

    r2 = client.post("/api/v1/admin/model-thresholds", json={"confidence_high": 0.95, "confidence_low": 0.70})
    assert r2.status_code == 401, f"Expected 401, got {r2.status_code}: {r2.text}"

    r3 = client.post("/api/v1/admin/carts", json={"cart_number": "CART-NO-AUTH"})
    assert r3.status_code == 401, f"Expected 401, got {r3.status_code}: {r3.text}"

    r4 = client.delete("/api/v1/products/some-unauthenticated-id")
    assert r4.status_code == 401, f"Expected 401, got {r4.status_code}: {r4.text}"


# =========================================================================
# TEST SUITE 2: STAFF ROLE PERMISSIONS (READ ALLOWED, PRIVILEGED ACTIONS 403)
# =========================================================================
def test_staff_role_permissions(test_users, sample_model, db_session):
    """
    Staff must be able to view live carts, alerts, review queue, and resolve alerts.
    Staff must receive 403 Forbidden on product deletion, threshold changes,
    model activation, model rollback, cart registration, and staff management.
    """
    staff_token = test_users["tokens"]["STAFF"]
    headers = {"Authorization": f"Bearer {staff_token}"}

    # Staff CAN view overview, carts, alerts, and review queue -> 200
    res_overview = client.get("/api/v1/admin/overview", headers=headers)
    assert res_overview.status_code == 200, f"Staff should view overview: {res_overview.text}"

    res_carts = client.get("/api/v1/admin/carts", headers=headers)
    assert res_carts.status_code == 200, f"Staff should view carts: {res_carts.text}"

    res_alerts = client.get("/api/v1/admin/alerts", headers=headers)
    assert res_alerts.status_code == 200, f"Staff should view alerts: {res_alerts.text}"

    res_reviews = client.get("/api/v1/admin/review-queue", headers=headers)
    assert res_reviews.status_code == 200, f"Staff should view review queue: {res_reviews.text}"

    # Staff CANNOT register carts -> 403
    res_reg_cart = client.post("/api/v1/admin/carts", json={"cart_number": "CART-STAFF-DENIED"}, headers=headers)
    assert res_reg_cart.status_code == 403, f"Staff cart registration should be 403: {res_reg_cart.status_code}"

    # Staff CANNOT update model thresholds -> 403
    res_thresh = client.post("/api/v1/admin/model-thresholds", json={"confidence_high": 0.95, "confidence_low": 0.70}, headers=headers)
    assert res_thresh.status_code == 403, f"Staff threshold update should be 403: {res_thresh.status_code}"

    # Staff CANNOT activate model -> 403
    m_id = sample_model["m2"].id
    res_act = client.post(f"/api/v1/admin/models/{m_id}/activate", headers=headers)
    assert res_act.status_code == 403, f"Staff model activation should be 403: {res_act.status_code}"

    # Staff CANNOT rollback model -> 403
    res_roll = client.post("/api/v1/admin/models/rollback", headers=headers)
    assert res_roll.status_code == 403, f"Staff model rollback should be 403: {res_roll.status_code}"

    # Staff CANNOT delete product -> 403
    temp_prod = Product(
        barcode=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Staff Test Product",
        brand="Test",
        category="General",
        price=10.0,
        is_active=True
    )
    db_session.add(temp_prod)
    db_session.commit()
    db_session.refresh(temp_prod)

    res_del = client.delete(f"/api/v1/products/{temp_prod.id}", headers=headers)
    assert res_del.status_code == 403, f"Staff product delete should be 403: {res_del.status_code}"

    # Staff CANNOT access staff management -> 403
    res_staff = client.get("/api/v1/auth/staff", headers=headers)
    assert res_staff.status_code == 403, f"Staff accessing /auth/staff should be 403: {res_staff.status_code}"


# =========================================================================
# TEST SUITE 3: MANAGER ROLE PERMISSIONS (200 ON PRIVILEGED ACTIONS)
# =========================================================================
def test_manager_role_permissions(test_users, sample_model, db_session):
    """
    Manager can update thresholds, delete products, activate/rollback models,
    register carts, and view audit logs (200 OK).
    Manager cannot manage staff accounts (Admin only -> 403).
    """
    mgr_token = test_users["tokens"]["MANAGER"]
    headers = {"Authorization": f"Bearer {mgr_token}"}

    # Manager CAN update thresholds -> 200
    res_thresh = client.post("/api/v1/admin/model-thresholds", json={"confidence_high": 0.94, "confidence_low": 0.65}, headers=headers)
    assert res_thresh.status_code == 200, f"Manager threshold update failed: {res_thresh.text}"
    assert res_thresh.json()["status"] == "SUCCESS"

    # Manager CAN activate model -> 200
    m_id = sample_model["m2"].id
    res_act = client.post(f"/api/v1/admin/models/{m_id}/activate", headers=headers)
    assert res_act.status_code == 200, f"Manager model activation failed: {res_act.text}"

    # Manager CAN roll back model -> 200
    res_roll = client.post("/api/v1/admin/models/rollback", headers=headers)
    assert res_roll.status_code == 200, f"Manager model rollback failed: {res_roll.text}"

    # Manager CAN register cart -> 200
    cart_num = f"MGR-CART-{uuid.uuid4().hex[:4].upper()}"
    res_reg = client.post("/api/v1/admin/carts", json={"cart_number": cart_num}, headers=headers)
    assert res_reg.status_code == 200, f"Manager cart registration failed: {res_reg.text}"

    # Manager CAN delete product -> 200
    prod_to_delete = Product(
        barcode=f"TEST-DEL-{uuid.uuid4().hex[:8]}",
        name="Manager Delete Product",
        brand="Test",
        category="General",
        price=15.0,
        is_active=True
    )
    db_session.add(prod_to_delete)
    db_session.commit()
    db_session.refresh(prod_to_delete)

    res_del = client.delete(f"/api/v1/products/{prod_to_delete.id}", headers=headers)
    assert res_del.status_code == 200, f"Manager product delete failed: {res_del.text}"

    # Manager CAN view audit logs -> 200
    res_audit = client.get("/api/v1/admin/audit-logs", headers=headers)
    assert res_audit.status_code == 200, f"Manager view audit logs failed: {res_audit.text}"
    assert "items" in res_audit.json()

    # Manager CANNOT access staff management -> 403
    res_staff = client.get("/api/v1/auth/staff", headers=headers)
    assert res_staff.status_code == 403, f"Manager accessing /auth/staff should be 403: {res_staff.status_code}"


# =========================================================================
# TEST SUITE 4: ADMIN ROLE PERMISSIONS (ADMIN-ONLY STAFF MANAGEMENT)
# =========================================================================
def test_admin_staff_management(test_users):
    """Admin-only: staff management."""
    admin_token = test_users["tokens"]["ADMIN"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    res_staff = client.get("/api/v1/auth/staff", headers=headers)
    assert res_staff.status_code == 200, f"Admin should access /auth/staff: {res_staff.text}"
    assert isinstance(res_staff.json(), list)


# =========================================================================
# TEST SUITE 5: SHOPPER SESSION AUTHORIZATION & ISOLATION
# =========================================================================
def test_shopper_session_isolation(sample_cart, db_session):
    """
    Shopper endpoints must enforce session authorization:
    - Session ID is unguessable UUID.
    - Session token is cryptographically random.
    - Access without token returns 401.
    - Access with another shopper's session token returns 403.
    """
    # Create two separate shopper sessions directly
    sess_a = CartSession(
        cart_id=sample_cart.id,
        session_token="token_shopper_AAA_" + uuid.uuid4().hex,
        status="ACTIVE"
    )
    sess_b = CartSession(
        cart_id=sample_cart.id,
        session_token="token_shopper_BBB_" + uuid.uuid4().hex,
        status="ACTIVE"
    )
    db_session.add(sess_a)
    db_session.add(sess_b)
    db_session.commit()
    db_session.refresh(sess_a)
    db_session.refresh(sess_b)

    # Confirm session IDs are 36-char unguessable UUIDs
    assert len(sess_a.id) == 36, "Session ID must be 36-character UUID"
    assert len(sess_b.id) == 36, "Session ID must be 36-character UUID"

    # 1. Shopper A accesses Session A with valid token -> 200
    res_ok = client.get(f"/api/v1/shopper/{sess_a.id}", headers={"X-Session-Token": sess_a.session_token})
    assert res_ok.status_code == 200, f"Shopper A valid access failed: {res_ok.text}"

    # 2. Access Session A without token -> 401
    res_unauth = client.get(f"/api/v1/shopper/{sess_a.id}")
    assert res_unauth.status_code == 401, f"Expected 401 for unauthenticated session access, got {res_unauth.status_code}"

    # 3. Shopper B attempts to access Session A using Shopper B's token -> 403
    res_cross = client.get(f"/api/v1/shopper/{sess_a.id}", headers={"X-Session-Token": sess_b.session_token})
    assert res_cross.status_code == 403, f"Expected 403 for cross-session access, got {res_cross.status_code}"

    # 4. Shopper B attempts to scan item into Session A -> 403
    res_scan_cross = client.post(
        f"/api/v1/shopper/{sess_a.id}/scan-item",
        json={"barcode": "8901030383838"},
        headers={"X-Session-Token": sess_b.session_token}
    )
    assert res_scan_cross.status_code == 403, f"Expected 403 for cross-session scan, got {res_scan_cross.status_code}"

    # 5. Shopper B attempts to checkout Session A -> 403
    res_checkout_cross = client.post(
        f"/api/v1/shopper/{sess_a.id}/checkout",
        json={"payment_method": "UPI"},
        headers={"X-Session-Token": sess_b.session_token}
    )
    assert res_checkout_cross.status_code == 403, f"Expected 403 for cross-session checkout, got {res_checkout_cross.status_code}"


# =========================================================================
# TEST SUITE 6: CONFIRM /exit ALIAS IS DELETED
# =========================================================================
def test_exit_alias_deleted(sample_cart, db_session):
    """
    POST /{session_id}/exit must return 404 (or 405) because the route has been completely deleted.
    POST /{session_id}/end-session is the only active route.
    """
    sess = CartSession(
        cart_id=sample_cart.id,
        session_token="token_exit_test_" + uuid.uuid4().hex,
        status="ACTIVE"
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)

    # 1. /exit must return 404 Not Found (or 405 Method Not Allowed)
    res_exit = client.post(f"/api/v1/shopper/{sess.id}/exit", headers={"X-Session-Token": sess.session_token})
    assert res_exit.status_code in [404, 405], f"Expected 404/405 for deleted /exit alias, got {res_exit.status_code}"

    # 2. /end-session must return 200
    res_end = client.post(f"/api/v1/shopper/{sess.id}/end-session", headers={"X-Session-Token": sess.session_token})
    assert res_end.status_code == 200, f"Expected 200 for /end-session, got {res_end.status_code}: {res_end.text}"
