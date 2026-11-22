import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.user import User
from app.utils.security import create_access_token
from app.main import app

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()

    # Seed admin user
    admin = User(
        id="user-p5-admin",
        email="admin@p5test.local",
        full_name="Phase 5 Admin",
        password_hash="hashed",
        role="ADMIN",
        is_active=True
    )
    # Seed manager user
    manager = User(
        id="user-p5-manager",
        email="manager@p5test.local",
        full_name="Phase 5 Manager",
        password_hash="hashed",
        role="MANAGER",
        is_active=True
    )
    # Seed test cart
    cart = Cart(
        id="cart-p5-01",
        cart_number="CART-05",
        qr_code_token="token-p5-01",
        device_token_hash="hash-p5-01",
        status="ACTIVE",
        camera_status="ONLINE"
    )
    session.add_all([admin, manager, cart])
    session.commit()

    yield session

    session.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_headers():
    token = create_access_token({"sub": "admin@p5test.local", "role": "ADMIN"})
    return {"Authorization": f"Bearer {token}"}


def test_rules_checklist_returns_all_10_rules(db_session, client, admin_headers):
    """Verify GET /api/v1/admin/rules/checklist returns complete matrix of R1-R10."""
    res = client.get("/api/v1/admin/rules/checklist", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["total_rules"] == 10
    rules = data["rules"]
    assert len(rules) == 10

    expected_rule_ids = [f"R{i}" for i in range(1, 11)]
    actual_rule_ids = [r["id"] for r in rules]
    assert actual_rule_ids == expected_rule_ids

    # Verify R1 to R10 required fields and status
    for r in rules:
        assert r["status"] == "ENFORCED"
        assert len(r["name"]) > 0
        assert len(r["summary"]) > 0
        assert len(r["enforcement"]) > 0
        assert len(r["reason_code"]) > 0
        assert len(r["privacy_gate"]) > 0


def test_rules_checklist_evaluates_cart_compliance(db_session, client, admin_headers):
    """Verify GET /api/v1/admin/rules/checklist evaluates live compliance when cart_id is provided."""
    sess_id = str(uuid.uuid4())
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p5-01",
        session_token="token-p5-sess",
        status="ACTIVE",
        cart_empty_verified=True
    )
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-p5-01",
        quantity=1,
        unit_price=10.0,
        status="VERIFIED"
    )
    db_session.add_all([cart_sess, item])
    db_session.commit()

    res = client.get("/api/v1/admin/rules/checklist?cart_id=cart-p5-01", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()

    status = data["cart_status"]
    assert status is not None
    assert status["cart_number"] == "CART-05"
    assert status["has_active_session"] is True
    assert status["cart_empty_verified"] is True
    assert status["r1_passed"] is True
    assert status["r2_passed"] is True
    assert status["r5_passed"] is True
    assert status["r6_passed"] is True
    assert status["r9_passed"] is True


def test_rules_checklist_unauthenticated_rejected(db_session, client):
    """Verify anonymous access is rejected."""
    res = client.get("/api/v1/admin/rules/checklist")
    assert res.status_code in (401, 403)


def test_verification_trace_and_rules_consistency(db_session, client, admin_headers):
    """Verify trace endpoint works alongside rules checklist for cart diagnostics."""
    res = client.get("/api/v1/admin/carts/cart-p5-01/verification-trace", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert "traces" in data
    assert data["cart_id"] == "cart-p5-01"
